//
//  ApplicationSectionLayout.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import { FormInput } from '@models/FormInput/FormInput.model';

const defaultProps = {
    title: 'Section title',
    intro: 'Section intro',
    compactType: 'psypact',
    applicationId: '2',
    isFormReady: true,
    submitFormInput: new FormInput({ isSubmitInput: true, id: 'submit-section' }),
};

describe('ApplicationSectionLayout component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(ApplicationSectionLayout, { props: defaultProps });

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(ApplicationSectionLayout).exists()).to.equal(true);
    });
    it('should render the header, slot content, and save button', async () => {
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: defaultProps,
            slots: {
                default: '<div class="slot-content">Content</div>',
                'after-form': '<div class="after-form-content">Modal</div>',
            },
        });

        expect(wrapper.find('.back-link').text()).to.equal('Back to checklist');
        expect(wrapper.find('.back-link').attributes('href')).to.equal('/psypact/Application/2');
        expect(wrapper.find('.section-title').text()).to.equal('Section title');
        expect(wrapper.find('.section-intro').text()).to.equal('Section intro');
        expect(wrapper.find('.section-form .slot-content').exists()).to.equal(true);
        expect(wrapper.find('.section-form .after-form-content').exists()).to.equal(false);
        expect(wrapper.find('.after-form-content').exists()).to.equal(true);
        expect(wrapper.find('.save-button input').attributes('value')).to.equal('Save');
        expect(wrapper.find('.continue-button').exists()).to.equal(false);
        expect(wrapper.find('.attention-banner').exists()).to.equal(false);
        expect(wrapper.find('.not-editable-message').exists()).to.equal(false);
        expect(wrapper.find('.mock-actions').exists()).to.equal(false);
    });
    it('should render mock populate and clear actions above the form when enabled', async () => {
        const onMockPopulate = sinon.spy();
        const onClear = sinon.spy();
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: {
                ...defaultProps,
                isMockPopulateEnabled: true,
                onMockPopulate,
                onClear,
            },
        });

        expect(wrapper.find('.section-body .mock-actions').exists()).to.equal(true);
        expect(wrapper.find('.clear-form').text()).to.equal('Clear');

        await wrapper.find('.mock-populate').trigger('click');
        await wrapper.find('.clear-form').trigger('click');

        expect(onMockPopulate.calledOnce).to.equal(true);
        expect(onClear.calledOnce).to.equal(true);
    });
    it('should not render the form until it is ready', async () => {
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: { ...defaultProps, isFormReady: false },
        });

        expect(wrapper.find('.section-form').exists()).to.equal(false);
    });
    it('should render a load error instead of the form', async () => {
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: { ...defaultProps, isLoadError: true },
        });

        expect(wrapper.find('.section-load-error').attributes('role')).to.equal('alert');
        expect(wrapper.find('.section-form').exists()).to.equal(false);
    });
    it('should render the needs attention banner with notes', async () => {
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: {
                ...defaultProps,
                isNeedsAttention: true,
                attentionNotes: ['First note', 'Second note'],
            },
        });

        expect(wrapper.find('.attention-banner').attributes('role')).to.equal('alert');
        expect(wrapper.find('.attention-title').text()).to.equal('Issue with your application');
        expect(wrapper.findAll('.attention-note').map((note) => note.text())).to.deep.equal([
            'First note',
            'Second note',
        ]);
    });
    it('should show a not editable message and disable saving', async () => {
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: { ...defaultProps, isEditable: false, isSaveEnabled: false },
        });

        expect(wrapper.find('.not-editable-message').exists()).to.equal(true);
        expect(wrapper.find('.save-button input').attributes('disabled')).to.not.equal(undefined);
    });
    it('should emit submit and continue events', async () => {
        const onSubmit = sinon.spy();
        const onContinue = sinon.spy();
        const wrapper = await mountFull(ApplicationSectionLayout, {
            props: {
                ...defaultProps,
                isSaveSuccessful: true,
                onSubmit,
                onContinue,
            },
        });

        await wrapper.find('.section-form').trigger('submit');
        await wrapper.find('.continue-button input').trigger('click');

        expect(onSubmit.calledOnce).to.equal(true);
        expect(onContinue.calledOnce).to.equal(true);
    });
});
