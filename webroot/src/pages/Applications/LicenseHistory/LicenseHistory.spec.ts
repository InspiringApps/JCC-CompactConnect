//
//  LicenseHistory.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import LicenseHistory from '@pages/Applications/LicenseHistory/LicenseHistory.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(LicenseHistory);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationLicenseHistory',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

const fillLicenseModal = async (component, values) => {
    const { licenseFormData } = component;

    licenseFormData.state.value = values.state;
    licenseFormData.issueDate.value = values.issueDate;
    licenseFormData.licenseNumber.value = values.licenseNumber;
    licenseFormData.status.value = values.status;
    await nextTick();
};

describe('LicenseHistory page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(LicenseHistory);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(LicenseHistory).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        expect(component.licenses.length).to.equal(2);

        await component.handleClearForm();

        expect(component.licenses.length).to.equal(0);
        expect(component.isFormValid).to.equal(false);
    });
    it('should display an empty license list and only the E.Passport inputs for an APIT application', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        expect(component.sectionKey).to.equal(ApplicationSection.LICENSE_HISTORY);
        expect(wrapper.find('.section-title').text()).to.equal('Licensure history');
        expect(wrapper.find('.licenses-table').exists()).to.equal(false);
        expect(wrapper.find('.no-licenses').exists()).to.equal(true);
        expect(wrapper.find('.e-passport-group').exists()).to.equal(true);
        expect(wrapper.find('.ipc-group').exists()).to.equal(false);
        expect(component.formData.ePassportNumber).to.not.equal(undefined);
        expect(component.formData.ipcNumber).to.equal(undefined);
    });
    it('should require at least one license and the E.Passport fields', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        component.validateAll({ asTouched: true, skipErrorScroll: true });
        await nextTick();

        expect(component.isFormValid).to.equal(false);
        expect(wrapper.find('.licenses-error').text()).to.equal('Add at least one license');
        expect(component.formData.ePassportNumber.errorMessage).to.equal('Required field');
    });
    it('should display existing licenses and both certifications for an APIT + TAP application', async () => {
        const wrapper = await mountPage('2');
        const rows = wrapper.findAll('.license-row');

        expect(rows.length).to.equal(2);
        expect(rows[0].find('.license-jurisdiction').text()).to.equal('Colorado');
        expect(rows[0].find('.license-number').text()).to.equal('1111111111');
        expect(rows[0].find('.license-status').text()).to.equal('Active');
        expect(rows[1].find('.license-jurisdiction').text()).to.equal('Kentucky');
        expect(wrapper.find('.e-passport-group').exists()).to.equal(true);
        expect(wrapper.find('.ipc-group').exists()).to.equal(true);
        expect(wrapper.vm.formData.ipcNumber.value).to.equal('2222222');
    });
    it('should add a license from the modal', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        await component.openLicenseModal();
        await nextTick();

        expect(wrapper.find('.license-modal').exists()).to.equal(true);
        expect(wrapper.find('.license-modal .modal-title').text()).to.equal('Add license');
        expect(component.licenseStatusOptions.map((option) => option.value)).to.matchPattern(['', 'active', 'inactive']);

        await fillLicenseModal(component, {
            state: 'ne',
            issueDate: '2020-01-15',
            licenseNumber: '3333',
            status: 'inactive',
        });
        component.saveLicense();
        await nextTick();

        expect(component.isLicenseModalOpen).to.equal(false);
        expect(component.licenses.length).to.equal(3);
        expect(component.licenses[2]).to.matchPattern({
            state: 'ne',
            issueDate: '2020-01-15',
            licenseNumber: '3333',
            status: 'inactive',
        });
        expect(wrapper.findAll('.license-row')[2].find('.license-jurisdiction').text()).to.equal('Nebraska');
    });
    it('should mock populate the license modal and scroll to its save button', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.openLicenseModal();
        await nextTick();
        await component.mockPopulateLicense();
        await nextTick();

        expect(scrollStub.calledOnceWith(component.licenseFormData.submit.id)).to.equal(true);
        expect(wrapper.find('.license-modal .license-form-row').exists()).to.equal(true);

        component.saveLicense();
        await nextTick();

        expect(component.isLicenseModalOpen).to.equal(false);
        expect(component.licenses[0]).to.matchPattern({
            state: 'co',
            issueDate: '2015-06-01',
            licenseNumber: 'PSY-0012345',
            status: 'active',
        });
    });
    it('should keep the modal open when the license inputs are invalid', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        await component.openLicenseModal();
        component.saveLicense();
        await nextTick();

        expect(component.isLicenseModalOpen).to.equal(true);
        expect(component.licenseFormData.state.errorMessage).to.equal('Required field');
        expect(component.licenses.length).to.equal(2);

        component.closeLicenseModal();
        await nextTick();

        expect(wrapper.find('.license-modal').exists()).to.equal(false);
    });
    it('should edit and remove licenses from the row menu', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        await wrapper.find('.license-menu-toggle').trigger('click');

        expect(wrapper.find('.license-menu').exists()).to.equal(true);

        await wrapper.find('.edit-license').trigger('click');
        await nextTick();

        expect(component.editLicenseIndex).to.equal(0);
        expect(component.licenseFormData.licenseNumber.value).to.equal('1111111111');
        expect(wrapper.find('.license-modal .modal-title').text()).to.equal('Edit license');

        component.licenseFormData.licenseNumber.value = '9999';
        await nextTick();
        component.saveLicense();

        expect(component.licenses.length).to.equal(2);
        expect(component.licenses[0].licenseNumber).to.equal('9999');

        component.removeLicense(1);

        expect(component.licenses.length).to.equal(1);
        expect(component.licenses[0].state).to.equal('co');
    });
    it('should prep the section request data', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;

        component.updateLicenses([{
            state: 'co',
            issueDate: '2020-01-15',
            licenseNumber: '1234',
            status: 'active',
        }]);
        component.formData.ePassportNumber.value = 'EP-1';
        component.formData.ePassportIssueDate.value = '2021-02-03';

        expect(component.prepSectionRequestData()).to.matchPattern({
            ePassport: { mobilityNumber: 'EP-1', issueDate: '2021-02-03' },
            ipc: component.applicationData.licenseHistory.ipc,
            licenses: [{
                state: 'co',
                issueDate: '2020-01-15',
                licenseNumber: '1234',
                status: 'active',
            }],
        });
    });
    it('should save the section with a single PATCH request', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        component.removeLicense(1);
        await component.handleSubmit();
        dispatchSpy.restore();

        const updateCalls = dispatchSpy.getCalls().filter((call) =>
            call.args[0] === 'user/updateApplicationRequestLicensee');

        expect(updateCalls.length).to.equal(1);
        expect(updateCalls[0].args[1].data.licenseHistory.licenses.length).to.equal(1);
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.licenseHistory.licenses.length).to.equal(1);
        expect(component.nextRoute).to.matchPattern({
            name: 'ApplicationEducation',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
});
