//
//  ConductHistory.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import ConductHistory from '@pages/Applications/ConductHistory/ConductHistory.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const convictionKey = 'attestation-convicted-of-a-criminal-offense';

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(ConductHistory);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationConductHistory',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

describe('ConductHistory page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(ConductHistory);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(ConductHistory).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        expect(component.formData[convictionKey].value).to.equal(false);

        component.formData[convictionKey].value = true;
        await nextTick();
        await nextTick();
        expect(component.convictionEntries.length).to.equal(1);

        await component.handleClearForm();
        await nextTick();

        expect(component.formData[convictionKey].value).to.equal(null);
        expect(component.convictionEntries.length).to.equal(0);
        expect(component.formData.convictionCharge0).to.equal(undefined);
        expect(component.isFormValid).to.equal(false);
    });
    it('should group the attestation questions and show the confirmation checkbox', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        expect(component.sectionKey).to.equal(ApplicationSection.CONDUCT_HISTORY);
        expect(wrapper.find('.section-title').text()).to.equal('Conduct history');
        expect(wrapper.findAll('.attestation-group .card-title').map((title) => title.text())).to.matchPattern([
            'Licensure actions',
            'Legal history',
            'Current proceedings',
            'Professional conduct',
        ]);
        expect(wrapper.findAll('.group-licensureActions .question-row').length).to.equal(8);
        expect(wrapper.findAll('.group-legalHistory .question-row').length).to.equal(2);
        expect(wrapper.findAll('.group-currentProceedings .question-row').length).to.equal(3);
        expect(wrapper.findAll('.group-professionalConduct .question-row').length).to.equal(8);
        expect(wrapper.find('.confirmation-checkbox').exists()).to.equal(true);
        expect(component.formData[convictionKey].value).to.equal(null);
        expect(wrapper.find('.conviction-panel').exists()).to.equal(false);
    });
    it('should append ungrouped attestations to the professional conduct group', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.fetchedApplication.conductHistory.attestations.push({
            attestationId: 'new-conduct-question',
            text: 'New question',
            version: '1',
            value: null,
        });

        const lastGroup = component.attestationGroups[component.attestationGroups.length - 1];

        expect(lastGroup.attestations[lastGroup.attestations.length - 1].attestationId)
            .to.equal('new-conduct-question');
    });
    it('should show conviction details when answering yes to the conviction question', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        component.formData[convictionKey].value = true;
        await nextTick();
        await nextTick();

        expect(wrapper.find('.conviction-panel').exists()).to.equal(true);
        expect(component.convictionEntries.length).to.equal(1);
        expect(component.formData.convictionCharge0).to.not.equal(undefined);
        expect(wrapper.find('.remove-conviction').exists()).to.equal(false);

        await wrapper.find('.add-conviction').trigger('click');

        expect(component.convictionEntries.length).to.equal(2);
        expect(component.formData.convictionCharge1).to.not.equal(undefined);
        expect(wrapper.findAll('.conviction-entry').length).to.equal(2);

        await wrapper.findAll('.remove-conviction')[0].trigger('click');

        expect(component.convictionEntries.length).to.equal(1);
        expect(component.formData.convictionCharge0).to.equal(undefined);
        expect(component.formData.convictionCharge1).to.not.equal(undefined);

        component.formData[convictionKey].value = false;
        await nextTick();
        await nextTick();

        expect(wrapper.find('.conviction-panel').exists()).to.equal(false);
        expect(component.formData.convictionCharge1).to.equal(undefined);
    });
    it('should require an explanation only when any question is answered yes', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;

        formData.notes.value = '';
        formData.notes.isTouched = true;
        formData.notes.validate();

        expect(formData.notes.isValid).to.equal(true);

        formData['attestation-registered-sex-offender'].value = true;
        await nextTick();

        expect(component.isAnyYes).to.equal(true);
        expect(formData.notes.isValid).to.equal(false);
        expect(formData.notes.errorMessage).to.equal('Required field');

        formData['attestation-registered-sex-offender'].value = false;
        await nextTick();

        expect(formData.notes.isValid).to.equal(true);
    });
    it('should display existing convictions and documents for a submitted application', async () => {
        const wrapper = await mountPage('3');
        const component = wrapper.vm;

        expect(component.isEditable).to.equal(false);
        expect(wrapper.find('.not-editable-message').exists()).to.equal(true);
        expect(wrapper.find('.save-button input').attributes('disabled')).to.not.equal(undefined);
        expect(component.formData.convictionCharge0.value).to.equal('Looting');
        expect(component.formData.convictionLocation0.value).to.equal('Los Angeles');
        expect(wrapper.findAll('.existing-files .file-name').map((file) => file.text()))
            .to.matchPattern(['document_1.pdf']);
    });
    it('should upload new documents and prep the section request data', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;
        const newFile = new File(['file contents'], 'new.pdf', { type: 'application/pdf' });

        formData[convictionKey].value = true;
        await nextTick();

        formData.convictionCharge0.value = 'Charge';
        formData.convictionLocation0.value = 'Denver';
        formData.convictionDate0.value = '2001-02-03';
        formData.convictionType0.value = 'Misdemeanor';
        formData.notes.value = 'Explanation';
        formData.documents.value = [newFile];

        const requestData: any = await component.prepSectionRequestData();

        expect(requestData.attestations.length).to.equal(22);
        expect(requestData.attestations.find((attestation) =>
            attestation.attestationId === 'convicted-of-a-criminal-offense')).to.matchPattern({
            attestationId: 'convicted-of-a-criminal-offense',
            version: '1',
            value: true,
        });
        expect(requestData.convictions).to.matchPattern([{
            charge: 'Charge',
            location: 'Denver',
            date: '2001-02-03',
            type: 'Misdemeanor',
        }]);
        expect(requestData.notes).to.equal('Explanation');
        expect(requestData.documents).to.matchPattern([
            { filename: 'document_1.pdf', sizeBytes: 2500000 },
            { filename: 'new.pdf', sizeBytes: newFile.size },
        ]);
    });
    it('should remove existing documents from the request data', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.removeExistingDocument(component.existingDocuments[0]);

        const requestData: any = await component.prepSectionRequestData();

        expect(requestData.documents).to.matchPattern([]);
        expect(requestData.convictions).to.matchPattern([]);
    });
    it('should save the section and route to the home state declaration next', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        component.formData.notes.value = 'Updated notes';
        await component.handleSubmit();
        dispatchSpy.restore();

        expect(dispatchSpy.calledWith('user/updateApplicationRequestLicensee')).to.equal(true);
        expect(dispatchSpy.calledWith('user/uploadApplicationDocumentsRequest')).to.equal(false);
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.conductHistory.notes).to.equal('Updated notes');
        expect(component.nextRoute).to.matchPattern({
            name: 'ApplicationHomeState',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
});
